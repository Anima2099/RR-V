from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
from uuid import uuid4

from app.general_preferences import (
    FILE_COLLISION_OVERWRITE,
    load_general_preferences,
)
from app.paths import find_executable
from app.thumbnail_log import (
    append_thumbnail_task_log,
    create_thumbnail_task_log_path,
    write_thumbnail_event,
)
from core.thumbnail_models import (
    OUTPUT_NEW_FILE,
    ThumbnailOptions,
    ThumbnailProbeResult,
    ThumbnailReplaceResult,
)


SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".mkv"}
SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


class ThumbnailCancelledError(RuntimeError):
    pass


class ThumbnailExecutionError(RuntimeError):
    def __init__(self, user_message: str, technical_detail: str = "") -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.technical_detail = technical_detail


class ThumbnailService:
    def __init__(self) -> None:
        self.ffmpeg = find_executable("ffmpeg.exe") or find_executable("ffmpeg")
        self.ffprobe = find_executable("ffprobe.exe") or find_executable("ffprobe")
        self._process: subprocess.Popen[str] | None = None
        self._process_lock = threading.Lock()

    def probe_existing_thumbnail(self, video_path: str) -> ThumbnailProbeResult:
        payload = self._probe_json(video_path)
        streams = payload.get("streams", [])
        if not isinstance(streams, list):
            streams = []
        cover_streams = self._cover_streams(streams)
        thumbnail_bytes = b""
        codec = ""
        if cover_streams and self.ffmpeg is not None:
            stream_index = int(cover_streams[0].get("index", -1))
            codec = str(cover_streams[0].get("codec_name", ""))
            if stream_index >= 0:
                thumbnail_bytes = self._extract_thumbnail_bytes(video_path, stream_index)
        return ThumbnailProbeResult(
            video_path=video_path,
            has_thumbnail=bool(cover_streams),
            thumbnail_bytes=thumbnail_bytes,
            thumbnail_codec=codec,
            stream_count=len(streams),
        )

    def replace_thumbnail(
        self,
        video_path: str,
        image_path: str,
        options: ThumbnailOptions,
        cancel_event: threading.Event,
    ) -> ThumbnailReplaceResult:
        if self.ffmpeg is None or self.ffprobe is None:
            raise ThumbnailExecutionError(
                "FFmpeg 또는 FFprobe를 찾을 수 없어서 썸네일 교체를 시작하지 못했습니다.",
                "설정 → 도구 및 리소스에서 FFmpeg와 FFprobe 상태를 확인해 주세요.",
            )

        video = Path(video_path)
        image = Path(image_path)
        if not video.is_file():
            raise ThumbnailExecutionError("영상 파일을 찾을 수 없습니다.", str(video))
        if not image.is_file():
            raise ThumbnailExecutionError("썸네일 이미지 파일을 찾을 수 없습니다.", str(image))
        if video.suffix.lower() not in SUPPORTED_VIDEO_EXTENSIONS:
            raise ThumbnailExecutionError(
                "이 영상 형식에는 아직 안전하게 썸네일을 넣을 수 없습니다.",
                "지원 형식: MP4, M4V, MOV, MKV",
            )
        if image.suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
            raise ThumbnailExecutionError(
                "지원하지 않는 이미지 형식입니다.",
                "지원 형식: JPG, JPEG, PNG, WebP",
            )

        task_log = create_thumbnail_task_log_path()
        write_thumbnail_event(
            "thumbnail.start",
            video=video,
            image=image,
            mode=options.output_mode,
            log=task_log,
        )
        append_thumbnail_task_log(
            task_log,
            (
                f"RR-V thumbnail replacement started: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"video={video}\nimage={image}\nmode={options.output_mode}\n"
                f"ffmpeg={self.ffmpeg}\nffprobe={self.ffprobe}\n\n"
            ),
        )

        payload = self._probe_json(str(video))
        streams = payload.get("streams", [])
        if not isinstance(streams, list):
            streams = []
        normal_video_streams = [
            stream
            for stream in streams
            if stream.get("codec_type") == "video"
            and not self._is_cover_stream(stream)
        ]
        if not normal_video_streams:
            raise ThumbnailExecutionError("영상 스트림을 찾을 수 없습니다.", str(video))
        cover_indices = [
            int(stream.get("index"))
            for stream in streams
            if self._is_cover_stream(stream) and str(stream.get("index", "")).isdigit()
        ]
        attachment_count = sum(
            1 for stream in streams if stream.get("codec_type") == "attachment"
        )

        temp_cover: Path | None = None
        temp_output = video.with_name(
            f".{video.stem}.rrv-thumb-{uuid4().hex[:8]}{video.suffix}"
        )
        try:
            temp_cover = self._prepare_cover_image(image, cancel_event, task_log)
            if cancel_event.is_set():
                raise ThumbnailCancelledError("썸네일 교체 중지됨")

            command = self._build_replace_command(
                video=video,
                cover=temp_cover,
                output=temp_output,
                cover_indices=cover_indices,
                normal_video_count=len(normal_video_streams),
                attachment_count=attachment_count,
            )
            self._run_ffmpeg(command, cancel_event, task_log)
            self._verify_output(temp_output)

            if options.output_mode == OUTPUT_NEW_FILE:
                final_output = self._resolve_new_output_path(video)
                if final_output.exists():
                    final_output.unlink()
                os.replace(temp_output, final_output)
                replaced_original = False
            else:
                final_output = video
                self._safe_replace_original(video, temp_output)
                replaced_original = True

            if options.delete_image_on_success and image.exists():
                try:
                    image.unlink()
                except OSError as error:
                    write_thumbnail_event(
                        "thumbnail.image_delete_failed",
                        image=image,
                        error=error,
                    )

            write_thumbnail_event(
                "thumbnail.success",
                video=video,
                output=final_output,
                replaced_original=replaced_original,
                log=task_log,
            )
            append_thumbnail_task_log(
                task_log,
                f"\nSUCCESS output={final_output}\n",
            )
            return ThumbnailReplaceResult(
                video_path=str(video),
                image_path=str(image),
                output_path=str(final_output),
                replaced_original=replaced_original,
            )
        except ThumbnailCancelledError:
            write_thumbnail_event("thumbnail.cancelled", video=video, log=task_log)
            raise
        except ThumbnailExecutionError:
            write_thumbnail_event("thumbnail.failed", video=video, log=task_log)
            raise
        except Exception as error:
            write_thumbnail_event(
                "thumbnail.failed",
                video=video,
                error=repr(error),
                log=task_log,
            )
            raise ThumbnailExecutionError(
                "썸네일을 교체하는 중 예상하지 못한 문제가 발생했습니다.",
                repr(error),
            ) from error
        finally:
            if temp_output.exists():
                try:
                    temp_output.unlink()
                except OSError:
                    pass
            if temp_cover is not None and temp_cover != image and temp_cover.exists():
                try:
                    temp_cover.unlink()
                except OSError:
                    pass

    def cancel(self) -> None:
        with self._process_lock:
            process = self._process
        if process is None or process.poll() is not None:
            return
        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    timeout=5,
                    check=False,
                )
            else:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except (OSError, subprocess.SubprocessError):
            try:
                process.kill()
            except OSError:
                pass

    def _probe_json(self, video_path: str) -> dict:
        if self.ffprobe is None:
            raise ThumbnailExecutionError("FFprobe를 찾을 수 없습니다.")
        command = [
            str(self.ffprobe),
            "-v", "error",
            "-show_streams",
            "-show_format",
            "-of", "json",
            video_path,
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=(
                    getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    if sys.platform == "win32"
                    else 0
                ),
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise ThumbnailExecutionError(
                "영상 정보를 확인하지 못했습니다.", str(error)
            ) from error
        if result.returncode != 0:
            raise ThumbnailExecutionError(
                "영상 정보를 확인하지 못했습니다.",
                result.stderr.strip() or result.stdout.strip(),
            )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise ThumbnailExecutionError(
                "FFprobe 응답을 해석하지 못했습니다.", str(error)
            ) from error
        return payload if isinstance(payload, dict) else {}

    def _extract_thumbnail_bytes(self, video_path: str, stream_index: int) -> bytes:
        if self.ffmpeg is None:
            return b""
        command = [
            str(self.ffmpeg),
            "-hide_banner",
            "-loglevel", "error",
            "-i", video_path,
            "-map", f"0:{stream_index}",
            "-frames:v", "1",
            "-f", "image2pipe",
            "-vcodec", "png",
            "pipe:1",
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                creationflags=(
                    getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    if sys.platform == "win32"
                    else 0
                ),
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return b""
        return result.stdout if result.returncode == 0 else b""

    def _prepare_cover_image(
        self,
        image: Path,
        cancel_event: threading.Event,
        task_log: Path,
    ) -> Path:
        if image.suffix.lower() in {".jpg", ".jpeg"}:
            return image
        if self.ffmpeg is None:
            raise ThumbnailExecutionError("FFmpeg를 찾을 수 없습니다.")
        fd, temp_name = tempfile.mkstemp(prefix="rrv_cover_", suffix=".jpg")
        os.close(fd)
        temp_path = Path(temp_name)
        command = [
            str(self.ffmpeg),
            "-hide_banner",
            "-y",
            "-i", str(image),
            "-frames:v", "1",
            "-q:v", "2",
            str(temp_path),
        ]
        try:
            self._run_ffmpeg(command, cancel_event, task_log)
            if not temp_path.is_file() or temp_path.stat().st_size <= 0:
                raise ThumbnailExecutionError(
                    "썸네일 이미지를 JPG로 준비하지 못했습니다.", str(image)
                )
            return temp_path
        except Exception:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def _build_replace_command(
        self,
        video: Path,
        cover: Path,
        output: Path,
        cover_indices: list[int],
        normal_video_count: int,
        attachment_count: int,
    ) -> list[str]:
        assert self.ffmpeg is not None
        suffix = video.suffix.lower()
        command = [str(self.ffmpeg), "-hide_banner", "-y", "-i", str(video)]

        if suffix == ".mkv":
            command.extend(["-map", "0"])
            for index in cover_indices:
                command.extend(["-map", f"-0:{index}"])
            command.extend([
                "-map_metadata", "0",
                "-map_chapters", "0",
                "-c", "copy",
                "-attach", str(cover),
                f"-metadata:s:t:{attachment_count}", "mimetype=image/jpeg",
                f"-metadata:s:t:{attachment_count}", "filename=cover.jpg",
                str(output),
            ])
            return command

        command.extend(["-i", str(cover), "-map", "0"])
        for index in cover_indices:
            command.extend(["-map", f"-0:{index}"])
        command.extend([
            "-map", "1:v:0",
            "-map_metadata", "0",
            "-map_chapters", "0",
            "-c", "copy",
            f"-disposition:v:{normal_video_count}", "attached_pic",
            f"-metadata:s:v:{normal_video_count}", "title=Cover",
            f"-metadata:s:v:{normal_video_count}", "comment=Cover (front)",
            str(output),
        ])
        return command

    def _run_ffmpeg(
        self,
        command: list[str],
        cancel_event: threading.Event,
        task_log: Path,
    ) -> None:
        append_thumbnail_task_log(
            task_log,
            "\ncommand=" + subprocess.list2cmdline(command) + "\n" + "-" * 72 + "\n",
        )
        creation_flags = 0
        popen_kwargs: dict[str, object] = {}
        if sys.platform == "win32":
            creation_flags = (
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            )
        else:
            popen_kwargs["start_new_session"] = True

        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creation_flags,
                **popen_kwargs,
            )
        except OSError as error:
            raise ThumbnailExecutionError("FFmpeg를 실행하지 못했습니다.", str(error)) from error

        with self._process_lock:
            self._process = process
        lines: list[str] = []
        try:
            assert process.stdout is not None
            for raw_line in process.stdout:
                line = raw_line.rstrip()
                append_thumbnail_task_log(task_log, line + "\n")
                lines.append(line)
                if len(lines) > 80:
                    lines.pop(0)
                if cancel_event.is_set():
                    self.cancel()
                    raise ThumbnailCancelledError("썸네일 교체 중지됨")
            return_code = process.wait()
        finally:
            with self._process_lock:
                self._process = None

        if cancel_event.is_set():
            raise ThumbnailCancelledError("썸네일 교체 중지됨")
        if return_code != 0:
            detail = "\n".join(lines[-50:])
            raise ThumbnailExecutionError(
                self._friendly_ffmpeg_error(detail),
                detail,
            )

    def _verify_output(self, output: Path) -> None:
        if not output.is_file() or output.stat().st_size <= 0:
            raise ThumbnailExecutionError("새 영상 파일이 정상적으로 만들어지지 않았습니다.")
        payload = self._probe_json(str(output))
        streams = payload.get("streams", [])
        if not isinstance(streams, list) or not self._cover_streams(streams):
            raise ThumbnailExecutionError(
                "새 영상에 썸네일이 실제로 들어갔는지 확인하지 못했습니다.",
                str(output),
            )

    def _safe_replace_original(self, original: Path, replacement: Path) -> None:
        backup = original.with_name(
            f".{original.stem}.rrv-thumb-backup-{uuid4().hex[:8]}{original.suffix}"
        )
        try:
            os.replace(original, backup)
            try:
                os.replace(replacement, original)
            except Exception:
                if backup.exists() and not original.exists():
                    os.replace(backup, original)
                raise
            if not original.is_file() or original.stat().st_size <= 0:
                if original.exists():
                    original.unlink(missing_ok=True)
                os.replace(backup, original)
                raise ThumbnailExecutionError(
                    "새 영상 확인에 실패해서 원본을 복구했습니다."
                )
            backup.unlink(missing_ok=True)
        except ThumbnailExecutionError:
            raise
        except OSError as error:
            if backup.exists() and not original.exists():
                try:
                    os.replace(backup, original)
                except OSError:
                    pass
            raise ThumbnailExecutionError(
                "원본 영상을 안전하게 교체하지 못했습니다.", str(error)
            ) from error

    def _resolve_new_output_path(self, video: Path) -> Path:
        stem = unicodedata.normalize("NFC", video.stem).strip() or "video"
        base = video.with_name(f"{stem}_thumbnail{video.suffix}")
        mode = load_general_preferences().file_collision_mode
        if mode == FILE_COLLISION_OVERWRITE or not base.exists():
            return base
        index = 2
        while True:
            candidate = video.with_name(f"{stem}_thumbnail ({index}){video.suffix}")
            if not candidate.exists():
                return candidate
            index += 1

    @staticmethod
    def _cover_streams(streams: list[dict]) -> list[dict]:
        return [stream for stream in streams if ThumbnailService._is_cover_stream(stream)]

    @staticmethod
    def _is_cover_stream(stream: dict) -> bool:
        disposition = stream.get("disposition", {})
        if isinstance(disposition, dict) and int(disposition.get("attached_pic", 0) or 0) == 1:
            return True
        tags = stream.get("tags", {})
        if not isinstance(tags, dict):
            return False
        mimetype = str(tags.get("mimetype", tags.get("MIMETYPE", ""))).lower()
        filename = str(tags.get("filename", tags.get("FILENAME", ""))).lower()
        return mimetype.startswith("image/") and bool(filename)

    @staticmethod
    def _friendly_ffmpeg_error(detail: str) -> str:
        lowered = detail.lower()
        if "permission denied" in lowered:
            return "영상 파일을 쓸 수 없습니다. 다른 프로그램에서 파일을 사용 중인지 확인해 주세요."
        if "could not find tag for codec" in lowered or "not currently supported in container" in lowered:
            return "이 영상 컨테이너에는 선택한 썸네일을 안전하게 넣을 수 없습니다."
        if "invalid data found" in lowered:
            return "영상이나 이미지 파일을 FFmpeg가 정상적으로 읽지 못했습니다."
        return "썸네일 교체에 실패했습니다."


def find_matching_image(video_path: str | Path) -> Path | None:
    video = Path(video_path)
    folder = video.parent
    stem = video.stem
    try:
        entries = [path for path in folder.iterdir() if path.is_file()]
    except OSError:
        return None

    image_by_name = {path.name.lower(): path for path in entries}
    for extension in (".jpg", ".jpeg", ".png", ".webp"):
        exact = image_by_name.get((stem + extension).lower())
        if exact is not None:
            return exact

    suffixes = (
        "_thumbnail",
        "-thumbnail",
        " thumbnail",
        "_thumb",
        "-thumb",
        ".cover",
        "_cover",
        "-cover",
    )
    for suffix in suffixes:
        for extension in (".jpg", ".jpeg", ".png", ".webp"):
            candidate = image_by_name.get((stem + suffix + extension).lower())
            if candidate is not None:
                return candidate

    stem_lower = stem.lower()
    candidates = sorted(
        (
            path
            for path in entries
            if path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
            and path.stem.lower().startswith(stem_lower)
        ),
        key=lambda path: (len(path.stem), path.name.lower()),
    )
    return candidates[0] if candidates else None


def scan_folder_for_tasks(folder_path: str | Path) -> list[tuple[Path, Path]]:
    folder = Path(folder_path)
    pairs: list[tuple[Path, Path]] = []
    if not folder.is_dir():
        return pairs
    try:
        video_paths = sorted(
            (
                path
                for path in folder.rglob("*")
                if path.is_file() and path.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS
            ),
            key=lambda path: str(path).lower(),
        )
    except OSError:
        return pairs
    for video in video_paths:
        image = find_matching_image(video)
        if image is not None:
            pairs.append((video, image))
    return pairs
