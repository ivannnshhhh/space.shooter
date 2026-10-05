from __future__ import annotations

import math
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from urllib.request import urlopen

import cv2

try:
    import mediapipe as mp
except Exception:  # pragma: no cover - handled gracefully during runtime
    mp = None

FACE_PADDING_X = 0.06
FACE_PADDING_Y = 0.08
FACE_LOST_GRACE_FRAMES = 90
FACE_TRACK_SMOOTHING = 0.4
FACE_BLUR_KERNEL_SIZE = 51
FACE_BLUR_SIGMA = 32
PINCH_THRESHOLD = 0.32
PINCH_RELEASE_THRESHOLD = 0.44
PINCH_DEBOUNCE_FRAMES = 2
INDEX_DEBOUNCE_FRAMES = 2
INDEX_EXTENSION_RATIO = 0.72
HANDEDNESS_INPUT_MIRRORED = True


def normalize_hand_label(media_pipe_label, mirrored_input=HANDEDNESS_INPUT_MIRRORED):
    label = str(media_pipe_label).upper()
    if label not in {"LEFT", "RIGHT"}:
        return "LEFT"
    if not mirrored_input:
        return "RIGHT" if label == "LEFT" else "LEFT"
    return label


@dataclass
class HandSnapshot:
    label: str
    landmarks: dict
    pinch: bool = False
    index_raised: bool = False
    move_left: bool = False
    move_right: bool = False
    trigger_play: bool = False
    trigger_tutorial: bool = False
    pinch_transition: bool = False
    index_transition: bool = False


class HandTracker:
    def __init__(self, max_hands: int = 2):
        self.max_hands = max_hands
        self.hands = None
        self.error_message = ""
        self.last_state = {}
        self.smoothed_landmarks = {}
        self.camera_frame = None
        self.hand_connections = ()
        self._tasks_api = False
        self._last_timestamp_ms = 0
        self.face_tracks = []

        self.face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        if self.face_cascade.empty():
            self.face_cascade = None

        if mp is None:
            self.error_message = "MediaPipe is unavailable in this environment. Hand gestures are disabled."
            return

        try:
            if hasattr(mp, "solutions") and hasattr(mp.solutions, "hands"):
                self.hand_connections = mp.solutions.hands.HAND_CONNECTIONS
                self.hands = mp.solutions.hands.Hands(
                    static_image_mode=False,
                    max_num_hands=max_hands,
                    min_detection_confidence=0.55,
                    min_tracking_confidence=0.55,
                )
            else:
                self._initialize_tasks_hands(max_hands)
        except Exception as exc:  # pragma: no cover
            self.error_message = f"MediaPipe initialization failed: {exc}"

    def _initialize_tasks_hands(self, max_hands):
        try:
            vision = mp.tasks.vision
            model_path = self._get_hand_model_path()
            options = vision.HandLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(model_asset_path=str(model_path)),
                running_mode=vision.RunningMode.VIDEO,
                num_hands=max_hands,
                min_hand_detection_confidence=0.55,
                min_hand_presence_confidence=0.55,
                min_tracking_confidence=0.55,
            )
            self.hands = vision.HandLandmarker.create_from_options(options)
            self.hand_connections = tuple(
                (connection.start, connection.end)
                for connection in vision.HandLandmarksConnections.HAND_CONNECTIONS
            )
            self._tasks_api = True
        except Exception as exc:
            self.error_message = f"MediaPipe Hands initialization failed: {exc}"

    def _get_hand_model_path(self):
        local_app_data = os.environ.get("LOCALAPPDATA")
        cache_root = Path(local_app_data) if local_app_data else Path.home() / ".cache"
        model_path = cache_root / "space_shooter" / "models" / "hand_landmarker.task"
        if model_path.is_file() and model_path.stat().st_size > 0:
            return model_path

        model_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = model_path.with_suffix(".task.tmp")
        model_url = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
        try:
            with urlopen(model_url, timeout=20) as response, temporary_path.open("wb") as model_file:
                shutil.copyfileobj(response, model_file)
            if temporary_path.stat().st_size == 0:
                raise OSError("Downloaded hand model is empty")
            temporary_path.replace(model_path)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
        return model_path

    def _distance(self, a, b):
        return math.hypot(a.x - b.x, a.y - b.y)

    def _landmark_position(self, landmarks, idx):
        lm = landmarks.landmark[idx]
        return (lm.x, lm.y)

    def _is_index_raised(self, landmarks):
        index_mcp = landmarks.landmark[5]
        index_pip = landmarks.landmark[6]
        index_dip = landmarks.landmark[7]
        index_tip = landmarks.landmark[8]
        wrist = landmarks.landmark[0]
        palm_scale = max(self._distance(wrist, landmarks.landmark[9]), 1e-4)
        finger_length = (
            self._distance(index_mcp, index_pip)
            + self._distance(index_pip, index_dip)
            + self._distance(index_dip, index_tip)
        )
        if finger_length <= 1e-4:
            return False
        extension = self._distance(index_mcp, index_tip) / finger_length
        vertical_margin = max(0.004, palm_scale * 0.025)
        return extension >= INDEX_EXTENSION_RATIO and index_tip.y < index_pip.y - vertical_margin

    def _is_pinch(self, landmarks, was_pinching=False):
        thumb_tip = landmarks.landmark[4]
        index_tip = landmarks.landmark[8]
        palm_scale = max(self._distance(landmarks.landmark[0], landmarks.landmark[9]), 1e-4)
        relative_distance = self._distance(thumb_tip, index_tip) / palm_scale
        threshold = PINCH_RELEASE_THRESHOLD if was_pinching else PINCH_THRESHOLD
        return relative_distance <= threshold

    @staticmethod
    def _debounce_state(value, previous, candidate_key, frames_key, state):
        candidate = state.get(candidate_key, previous)
        frames = state.get(frames_key, 0)
        if value == previous:
            return previous, previous, 0
        if value != candidate:
            candidate = value
            frames = 1
        else:
            frames += 1
        if frames >= (PINCH_DEBOUNCE_FRAMES if candidate_key == "pinch_candidate" else INDEX_DEBOUNCE_FRAMES):
            return candidate, candidate, 0
        return previous, candidate, frames

    def _draw_hand(self, frame, hand_landmarks, label, pinch, index_raised):
        height, width = frame.shape[:2]
        max_x = max(1, width - 1)
        max_y = max(1, height - 1)
        points = []
        previous_points = self.smoothed_landmarks.get(label)
        for idx, landmark in enumerate(hand_landmarks.landmark):
            point = (landmark.x * max_x, landmark.y * max_y)
            if previous_points is not None:
                old_x, old_y = previous_points[idx]
                point = (old_x * max_x * 0.35 + point[0] * 0.65, old_y * max_y * 0.35 + point[1] * 0.65)
            points.append((int(round(point[0])), int(round(point[1]))))
        self.smoothed_landmarks[label] = [(x / max_x, y / max_y) for x, y in points]

        hand_color = (0, 220, 255) if label == "LEFT" else (255, 80, 220)
        for start_idx, end_idx in self.hand_connections:
            cv2.line(frame, points[start_idx], points[end_idx], hand_color, 2, cv2.LINE_AA)

        fingertips = {4, 8, 12, 16, 20}
        for idx, point in enumerate(points):
            color = hand_color
            radius = 4
            if idx in fingertips:
                color = (255, 255, 255)
                radius = 6
            if idx == 8 and index_raised:
                color = (0, 255, 0)
            if pinch and idx in {4, 8}:
                color = (0, 255, 255)
                radius = 7
            cv2.circle(frame, point, radius, color, -1, cv2.LINE_AA)
            if idx in fingertips:
                cv2.circle(frame, point, radius, (20, 20, 20), 1, cv2.LINE_AA)

        if pinch:
            cv2.line(frame, points[4], points[8], (0, 255, 255), 3, cv2.LINE_AA)

    def _detect_faces(self, frame):
        if frame is None or frame.size == 0 or self.face_cascade is None:
            return []
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self.face_cascade.detectMultiScale(gray, scaleFactor=1.08, minNeighbors=4, minSize=(40, 40))
        return [tuple(map(int, face)) for face in faces]

    def _face_match_score(self, first, second):
        first_x, first_y, first_w, first_h = first
        second_x, second_y, second_w, second_h = second
        left = max(first_x, second_x)
        top = max(first_y, second_y)
        right = min(first_x + first_w, second_x + second_w)
        bottom = min(first_y + first_h, second_y + second_h)
        intersection = max(0, right - left) * max(0, bottom - top)
        union = first_w * first_h + second_w * second_h - intersection
        overlap = intersection / union if union else 0.0

        first_center = (first_x + first_w / 2, first_y + first_h / 2)
        second_center = (second_x + second_w / 2, second_y + second_h / 2)
        face_scale = max(first_w, first_h, second_w, second_h, 1)
        center_distance = math.hypot(
            first_center[0] - second_center[0],
            first_center[1] - second_center[1],
        ) / face_scale

        if overlap >= 0.05:
            return 1.0 - overlap
        if center_distance <= 1.75:
            return 1.0 + center_distance
        return None

    def _update_face_tracks(self, detections):
        available_tracks = set(range(len(self.face_tracks)))
        updated_tracks = list(self.face_tracks)

        for detection in detections:
            best_index = None
            best_score = float("inf")
            for index in available_tracks:
                score = self._face_match_score(updated_tracks[index]["box"], detection)
                if score is not None and score < best_score:
                    best_index = index
                    best_score = score

            if best_index is None:
                updated_tracks.append({"box": tuple(map(float, detection)), "missed_frames": 0})
                continue

            track = updated_tracks[best_index]
            old_box = track["box"]
            amount = FACE_TRACK_SMOOTHING
            track["box"] = tuple(
                old_value * (1.0 - amount) + new_value * amount
                for old_value, new_value in zip(old_box, detection)
            )
            track["missed_frames"] = 0
            available_tracks.remove(best_index)

        for index in available_tracks:
            updated_tracks[index]["missed_frames"] += 1

        self.face_tracks = [
            track
            for track in updated_tracks
            if track["missed_frames"] <= FACE_LOST_GRACE_FRAMES
        ]
        return [tuple(int(round(value)) for value in track["box"]) for track in self.face_tracks]

    def _blur_face_regions(self, frame, faces):
        height, width = frame.shape[:2]
        for x, y, face_width, face_height in faces:
            padding_x = int(round(face_width * FACE_PADDING_X))
            padding_y = int(round(face_height * FACE_PADDING_Y))
            left = max(0, x - padding_x)
            top = max(0, y - padding_y)
            right = min(width, x + face_width + padding_x)
            bottom = min(height, y + face_height + padding_y)
            region = frame[top:bottom, left:right]
            if region.size:
                frame[top:bottom, left:right] = cv2.GaussianBlur(
                    region,
                    (FACE_BLUR_KERNEL_SIZE, FACE_BLUR_KERNEL_SIZE),
                    FACE_BLUR_SIGMA,
                )

    def process_frame(self, frame):
        self.camera_frame = frame.copy() if frame is not None else None
        result = {"hands": [], "faces": [], "debug_frame": frame.copy() if frame is not None else None}

        if frame is None or frame.size == 0:
            return result

        result["faces"] = self._update_face_tracks(self._detect_faces(frame))
        raw_frame = frame.copy()
        blurred = raw_frame.copy()
        self._blur_face_regions(blurred, result["faces"])
        result["debug_frame"] = blurred

        if self.hands is None:
            return result

        rgb = cv2.cvtColor(raw_frame, cv2.COLOR_BGR2RGB)
        if self._tasks_api:
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            timestamp_ms = max(self._last_timestamp_ms + 1, int(time.monotonic() * 1000))
            self._last_timestamp_ms = timestamp_ms
            detection = self.hands.detect_for_video(image, timestamp_ms)
            detected_landmarks = [SimpleNamespace(landmark=points) for points in detection.hand_landmarks]
            handedness_results = detection.handedness
        else:
            detection = self.hands.process(rgb)
            detected_landmarks = detection.multi_hand_landmarks or []
            handedness_results = detection.multi_handedness or []

        if not detected_landmarks:
            self.smoothed_landmarks.clear()
            return result

        hand_overlay = raw_frame.copy()
        hand_overlay.fill(0)
        detected_labels = set()
        for idx, hand_landmarks in enumerate(detected_landmarks):
            handedness = "Left"
            if idx < len(handedness_results) and handedness_results[idx]:
                classification = handedness_results[idx][0] if self._tasks_api else handedness_results[idx].classification[0]
                handedness = getattr(classification, "label", None) or getattr(classification, "category_name", "Left")
            media_pipe_label = "LEFT" if str(handedness).lower() == "left" else "RIGHT"
            label = normalize_hand_label(media_pipe_label)
            detected_labels.add(label)
            previous = self.last_state.get(label, {"pinch": False, "index_raised": False})
            pinched_before = bool(previous.get("pinch", False))
            index_before = bool(previous.get("index_raised", False))
            raw_pinch = self._is_pinch(hand_landmarks, pinched_before)
            pinch, pinch_candidate, pinch_frames = self._debounce_state(
                raw_pinch,
                pinched_before,
                "pinch_candidate",
                "pinch_frames",
                previous,
            )
            raw_index_raised = self._is_index_raised(hand_landmarks)
            index_raised, index_candidate, index_frames = self._debounce_state(
                raw_index_raised,
                index_before,
                "index_candidate",
                "index_frames",
                previous,
            )

            pinch_transition = pinched_before and not pinch and index_raised
            index_transition = index_before and not index_raised and pinch

            movement_active = bool(
                not pinch
                and index_raised
                and (pinch_transition or previous.get("movement_active", False))
            )
            move_left = bool(label == "LEFT" and movement_active)
            move_right = bool(label == "RIGHT" and movement_active)

            trigger_play = label == "RIGHT" and pinched_before and index_raised and not pinch
            trigger_tutorial = label == "LEFT" and pinched_before and index_raised and not pinch

            self.last_state[label] = {
                "pinch": pinch,
                "index_raised": index_raised,
                "pinch_candidate": pinch_candidate,
                "pinch_frames": pinch_frames,
                "index_candidate": index_candidate,
                "index_frames": index_frames,
                "movement_active": movement_active,
            }
            self._draw_hand(
                hand_overlay,
                hand_landmarks,
                label,
                pinch,
                index_raised,
            )

            snapshot = HandSnapshot(
                label=label,
                landmarks={
                    "thumb_tip": self._landmark_position(hand_landmarks, 4),
                    "index_finger_tip": self._landmark_position(hand_landmarks, 8),
                    "index_finger_mcp": self._landmark_position(hand_landmarks, 5),
                    "wrist": self._landmark_position(hand_landmarks, 0),
                },
                pinch=bool(pinch),
                index_raised=bool(index_raised),
                move_left=bool(move_left),
                move_right=bool(move_right),
                trigger_play=bool(trigger_play),
                trigger_tutorial=bool(trigger_tutorial),
                pinch_transition=bool(pinch_transition),
                index_transition=bool(index_transition),
            )
            result["hands"].append(snapshot)

        for label in set(self.smoothed_landmarks) - detected_labels:
            self.smoothed_landmarks.pop(label, None)

        overlay_mask = cv2.cvtColor(hand_overlay, cv2.COLOR_BGR2GRAY) > 0
        final_frame = blurred.copy()
        final_frame[overlay_mask] = hand_overlay[overlay_mask]
        result["debug_frame"] = final_frame
        return result

    def draw_debug_overlay(self, frame, hands, faces):
        return frame.copy() if frame is not None else None

    def get_hand_by_label(self, hands, label):
        for hand in hands:
            if hand.label == label:
                return hand
        return None

    def close(self):
        if self.hands is not None:
            self.hands.close()
