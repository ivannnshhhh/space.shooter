from __future__ import annotations

import os
import threading
import time

import cv2
import numpy as np
import pygame


class CameraManager:
    OPEN_TIMEOUT_SECONDS = 1.5
    FRAME_TIMEOUT_SECONDS = 1.5
    RETRY_INTERVAL_SECONDS = 0.75
    STATUS_POLL_SECONDS = 0.1

    def __init__(self, camera_index: int = 0, width: int = 640, height: int = 480):
        self.camera_index = camera_index
        self.width = width
        self.height = height
        self.cap = None
        self.frame = np.zeros((height, width, 3), dtype=np.uint8)
        self.camera_error = "Initializing camera..."

        self._lock = threading.Lock()
        self._closed = False
        self._stop_event = threading.Event()
        self._retry_at = 0.0
        self._open_attempts = {}
        self._capture_generation = 0
        self._capture_started_at = None
        self._last_frame_at = None
        self._latest_frame = None
        self._frame_sequence = 0
        self._consumed_sequence = 0
        self._reader_thread = None
        self._fallback_backend = cv2.CAP_DSHOW if os.name == "nt" else None
        self._open_camera()

    def _open_camera(self):
        now = time.monotonic()
        workers_to_start = []

        with self._lock:
            if self._closed or self.cap is not None or now < self._retry_at:
                return

            default_attempt = self._open_attempts.get("default")
            fallback_attempt = self._open_attempts.get("fallback")

            def schedule_attempt(name, backend):
                attempt = {"started_at": now, "done": False, "success": False}
                worker = threading.Thread(
                    target=self._open_camera_attempt,
                    args=(name, backend, attempt),
                    daemon=True,
                    name=f"camera-open-{name}",
                )
                attempt["thread"] = worker
                self._open_attempts[name] = attempt
                workers_to_start.append(worker)

            if default_attempt is None:
                schedule_attempt("default", None)
                self.camera_error = "Initializing camera..."
            elif (
                self._fallback_backend is not None
                and fallback_attempt is None
                and (
                    (default_attempt["done"] and not default_attempt["success"])
                    or now - default_attempt["started_at"] >= self.OPEN_TIMEOUT_SECONDS
                )
            ):
                schedule_attempt("fallback", self._fallback_backend)
                self.camera_error = "Camera open timed out; trying DirectShow..."
            elif (
                self._fallback_backend is not None
                and fallback_attempt is not None
                and fallback_attempt["done"]
                and not fallback_attempt["success"]
            ):
                self.camera_error = "Camera unavailable; retrying DirectShow..."
                schedule_attempt("fallback", self._fallback_backend)
            elif (
                self._fallback_backend is None
                and default_attempt["done"]
                and not default_attempt["success"]
            ):
                self.camera_error = "Camera unavailable; retrying..."
                self._open_attempts.clear()
                schedule_attempt("default", None)
            elif fallback_attempt is not None and not fallback_attempt["done"]:
                self.camera_error = "Opening camera with DirectShow..."
            elif default_attempt is not None and not default_attempt["done"]:
                self.camera_error = "Initializing camera..."

        for worker in workers_to_start:
            worker.start()

    def _open_camera_attempt(self, name, backend, attempt):
        capture = None
        reader_data = None
        error = "Camera did not open."
        success = False
        try:
            if backend is None:
                capture = cv2.VideoCapture(self.camera_index)
            else:
                capture = cv2.VideoCapture(self.camera_index, backend)

            if capture is not None and capture.isOpened():
                capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                capture.set(cv2.CAP_PROP_FPS, 30)
                with self._lock:
                    if not self._closed and self.cap is None:
                        self._capture_generation += 1
                        generation = self._capture_generation
                        self.cap = capture
                        self._capture_started_at = time.monotonic()
                        self._last_frame_at = None
                        self._latest_frame = None
                        self._frame_sequence = 0
                        self._consumed_sequence = 0
                        self.camera_error = ""
                        reader_data = (capture, generation)
                        success = True
                        capture = None
                    elif not self._closed:
                        success = True
            else:
                error = f"{name} camera backend could not open device {self.camera_index}."
        except Exception as exc:
            error = f"{name} camera backend failed: {exc}"
        finally:
            if capture is not None:
                self._release_capture_async(capture)
            with self._lock:
                attempt["done"] = True
                attempt["success"] = success
                attempt["error"] = error
                if not success and not self._closed and self.cap is None:
                    self.camera_error = error
                    self._retry_at = time.monotonic() + self.RETRY_INTERVAL_SECONDS

        if reader_data is not None:
            capture_obj, generation = reader_data
            reader = threading.Thread(
                target=self._read_camera_loop,
                args=(capture_obj, generation),
                daemon=True,
                name="camera-frame-reader",
            )
            watchdog = threading.Thread(
                target=self._watch_camera_frames,
                args=(capture_obj, generation),
                daemon=True,
                name="camera-frame-watchdog",
            )
            with self._lock:
                should_start = not self._closed and generation == self._capture_generation
                if should_start:
                    self._reader_thread = reader
            if should_start:
                reader.start()
                watchdog.start()

    @staticmethod
    def _release_capture(capture):
        if capture is not None:
            try:
                capture.release()
            except Exception:
                pass

    def _release_capture_async(self, capture):
        if capture is not None:
            threading.Thread(
                target=self._release_capture,
                args=(capture,),
                daemon=True,
                name="camera-capture-release",
            ).start()

    def _invalidate_capture(self, capture, reason):
        with self._lock:
            if self._closed or self.cap is not capture:
                return False
            self.cap = None
            self._capture_generation += 1
            self._latest_frame = None
            self._open_attempts.clear()
            self._retry_at = time.monotonic() + self.RETRY_INTERVAL_SECONDS
            self.camera_error = reason
        self._release_capture_async(capture)
        return True

    def _read_camera_loop(self, capture, generation):
        while True:
            with self._lock:
                if self._closed or self.cap is not capture or self._capture_generation != generation:
                    return

            try:
                ok, frame = capture.read()
            except Exception as exc:
                self._invalidate_capture(capture, f"Camera frame read failed: {exc}")
                return
            if not ok or frame is None:
                self._invalidate_capture(capture, "Camera frame unavailable; reconnecting...")
                return

            flipped = cv2.flip(frame, 1)
            now = time.monotonic()
            with self._lock:
                if self._closed or self.cap is not capture or self._capture_generation != generation:
                    return
                self.frame = flipped
                self._latest_frame = flipped
                self._frame_sequence += 1
                self._last_frame_at = now
                self.camera_error = ""

    def _watch_camera_frames(self, capture, generation):
        while not self._stop_event.wait(self.STATUS_POLL_SECONDS):
            with self._lock:
                if self._closed or self.cap is not capture or self._capture_generation != generation:
                    return
                last_frame_at = self._last_frame_at or self._capture_started_at or time.monotonic()
                timed_out = time.monotonic() - last_frame_at > self.FRAME_TIMEOUT_SECONDS
            if timed_out:
                self._invalidate_capture(capture, "Camera frames timed out; reconnecting...")
                return

    def read_frame(self):
        if not self.is_available():
            return None
        with self._lock:
            if self._latest_frame is None or self._frame_sequence == self._consumed_sequence:
                return None
            frame = self._latest_frame.copy()
            self._consumed_sequence = self._frame_sequence
        return frame

    def get_surface(self, target_size=None):
        if target_size is None:
            target_size = (self.width, self.height)
        if self.frame.size == 0:
            return pygame.Surface(target_size, pygame.SRCALPHA)
        rgb = cv2.cvtColor(self.frame, cv2.COLOR_BGR2RGB)
        pygame_image = pygame.image.frombuffer(rgb.tobytes(), rgb.shape[1::-1], "RGB")
        if target_size != rgb.shape[1::-1]:
            pygame_image = pygame.transform.smoothscale(pygame_image, target_size)
        return pygame_image

    def close(self):
        with self._lock:
            self._closed = True
            capture = self.cap
            self.cap = None
            self._capture_generation += 1
            self._latest_frame = None
            self._stop_event.set()
        self._release_capture_async(capture)

    def is_available(self):
        with self._lock:
            capture = self.cap
            closed = self._closed
            if capture is not None:
                last_frame_at = self._last_frame_at or self._capture_started_at or time.monotonic()
                if time.monotonic() - last_frame_at <= self.FRAME_TIMEOUT_SECONDS:
                    return True

        if capture is not None and not closed:
            self._invalidate_capture(capture, "Camera frames timed out; reconnecting...")
        if not closed:
            self._open_camera()
        with self._lock:
            return not self._closed and self.cap is not None