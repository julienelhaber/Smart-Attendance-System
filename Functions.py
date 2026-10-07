from database import add_student, mark_attendance, student_exists, get_student_by_email
from dotenv import load_dotenv
import subprocess
import sys
import cv2
import os
import shutil
import tkinter.messagebox as messagebox
import customtkinter as ctk
import random
import smtplib
import re
import time
from email.message import EmailMessage
from collections import deque
from math import hypot

FACE_SIZE = (200, 200)
CONFIDENCE_LIMIT = 70
REQUIRED_STABLE_FRAMES = 5
# How many face images are captured when registering a new student.
REGISTRATION_IMAGE_COUNT = 20

# Anti-spoofing settings.
# This version avoids application crashes by using OpenCV Haar eye detection only.
# A valid blink must follow this sequence:
# eyes visible/open -> eyes closed or temporarily not visible -> eyes visible/open again.
OPEN_EYE_FRAMES_REQUIRED = 3
# A natural blink keeps the eyes fully closed for only ~100ms, which is a
# single frame at this loop's processing rate. Requiring 2 consecutive
# closed frames made fast blinks invisible; the stable open phase before and
# reopen phase after (plus the head-motion guards) still block noise.
CLOSED_EYE_FRAMES_REQUIRED = 1
REOPEN_EYE_FRAMES_REQUIRED = 2
MAX_CLOSED_EYE_FRAMES = 15
REQUIRED_BLINKS = 1
# Haar eye detection only works on frontal faces, so a head turn makes the
# eyes "disappear" exactly like a blink. Frames where the face box moves more
# than this fraction of its width are skipped (not counted as open or closed).
# Skipping instead of restarting matters: closing the eyes makes the Haar
# face box itself jump for a frame, which used to cancel the very blink
# being performed.
HEAD_MOVE_TOLERANCE = 0.06
# Restart the sequence if the face drifts this far (fraction of face width)
# from the anchor position while a blink is in progress.
HEAD_DRIFT_TOLERANCE = 0.15
# While the eyes are open the anchor slowly follows the face, so normal
# sitting drift is forgiven. It freezes during the blink itself, so turning
# the head mid-blink still trips the drift check above.
ANCHOR_FOLLOW_RATE = 0.2
# When Haar reports the eyes gone, each eye region is compared against how
# it looked while open. A real blink closes BOTH eyes at once, so if either
# region still matches its open snapshot at this correlation, no blink
# happened (detector dropout, or glare on the other lens). A dropout frame
# is pixel-identical (~0.95+); a closed eyelid scores far lower, so this
# must stay high or real blinks get eaten.
DROPOUT_SIMILARITY = 0.90
# Eyeglass glare is near-white; an eyelid is skin. If the fraction of
# near-saturated pixels in an eye region jumps by more than this while the
# eyes are "gone", the frame is a glare flash and not a blink.
GLARE_BRIGHT_LEVEL = 230
GLARE_FRACTION_JUMP = 0.06
LIVENESS_TIMEOUT_FRAMES = 350
FACE_CENTER_HISTORY = 20
NO_FACE_TIMEOUT_FRAMES = 350

# Email verification codes are stored as {email: (code, sent_timestamp)} and
# expire after this many seconds.
VERIFICATION_CODE_TTL_SECONDS = 5 * 60
verification_codes = {}


def _get_valid_verification_code(student_email):
    """Return the pending code for this email, or None if there is none or
    it has expired (expired codes are removed)."""
    entry = verification_codes.get(student_email)
    if entry is None:
        return None
    code, sent_at = entry
    if time.time() - sent_at > VERIFICATION_CODE_TTL_SECONDS:
        verification_codes.pop(student_email, None)
        return None
    return code
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

load_dotenv(os.path.join(SCRIPT_DIR, ".env"))

def _open_camera():
    import platform
    # On Mac, use AVFoundation backend. On Windows, try DirectShow first.
    if platform.system() == "Darwin":
        backends = (cv2.CAP_AVFOUNDATION, cv2.CAP_ANY)
    else:
        backends = (cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY)

    for index in (0, 1):
        for backend in backends:
            camera = cv2.VideoCapture(index, backend)
            if camera.isOpened():
                camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                return camera
            camera.release()

    return cv2.VideoCapture(0)


def _face_detector():
    return cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )


def _eye_detectors():
    """Regular eye cascade plus the eyeglasses-trained one as a fallback,
    so students wearing glasses still get stable open-eye detection."""
    return (
        cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye.xml"),
        cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye_tree_eyeglasses.xml"),
    )


def _safe_close_camera(camera):
    """Release OpenCV resources without crashing Tkinter/OpenCV."""
    try:
        if camera is not None:
            camera.release()
    except Exception:
        pass
    try:
        cv2.destroyAllWindows()
    except Exception:
        pass


def _reset_blink_phase(liveness_state):
    """Restart the open -> closed -> open sequence without touching blink_count."""
    liveness_state["open_eye_frames"] = 0
    liveness_state["closed_eye_frames"] = 0
    liveness_state["reopen_eye_frames"] = 0
    liveness_state["ready_for_blink"] = False
    liveness_state["waiting_for_reopen"] = False
    liveness_state["blink_anchor"] = None
    liveness_state["eye_templates"] = None


def _count_real_eyes(detections, region_width):
    """A face has at most one eye on each side. Haar often fires extra boxes
    on eyebrows or glasses glare, so collapse the raw detections into how
    many sides of the face actually show an eye: 0, 1 or 2."""
    left_side = False
    right_side = False
    for (ex, ey, ew, eh) in detections:
        if ex + ew / 2.0 < region_width / 2.0:
            left_side = True
        else:
            right_side = True
    return int(left_side) + int(right_side)


def _capture_eye_templates(upper_face, detections):
    """Remember how each open eye currently looks (largest box per side),
    so a later "eyes disappeared" frame can be checked against it.

    Only the central part of the Haar box is stored: the box also covers
    eyebrow and skin, which do not change during a blink and would make a
    closed eye still look "unchanged"."""
    mid = upper_face.shape[1] / 2.0
    best = {}
    for (ex, ey, ew, eh) in detections:
        side = "left" if ex + ew / 2.0 < mid else "right"
        if side not in best or ew * eh > best[side][2] * best[side][3]:
            best[side] = (ex, ey, ew, eh)
    templates = []
    for (ex, ey, ew, eh) in best.values():
        crop_x = ew // 4
        crop_y = eh // 4
        if ew - 2 * crop_x >= 8 and eh - 2 * crop_y >= 6:
            ex, ey = ex + crop_x, ey + crop_y
            ew, eh = ew - 2 * crop_x, eh - 2 * crop_y
        patch = upper_face[ey:ey + eh, ex:ex + ew]
        if patch.size > 0:
            templates.append(((ex, ey, ew, eh), patch.copy()))
    return templates


def _not_a_real_blink(upper_face, templates):
    """True when a "no eyes found" frame should NOT count as closed eyes.

    Two tells, checked per eye against the stored open-eye patches:
    - the region still matches its open snapshot: that eye is clearly still
      open (detector dropout, or glare hid only the other lens), and a real
      blink always closes both eyes at once;
    - the region gained a burst of near-saturated pixels: glasses glare,
      not an eyelid.
    """
    if not templates:
        return False
    for (ex, ey, ew, eh), patch in templates:
        # Search a padded window so small face-box jitter cannot hide a match.
        pad = max(6, ew // 2)
        x0 = max(0, ex - pad)
        y0 = max(0, ey - pad)
        x1 = min(upper_face.shape[1], ex + ew + pad)
        y1 = min(upper_face.shape[0], ey + eh + pad)
        window = upper_face[y0:y1, x0:x1]
        if window.shape[0] < eh or window.shape[1] < ew:
            return False
        result = cv2.matchTemplate(window, patch, cv2.TM_CCOEFF_NORMED)
        _, similarity, _, best_loc = cv2.minMaxLoc(result)
        if similarity != similarity:  # NaN from a flat patch: cannot judge
            similarity = 1.0
        if similarity >= DROPOUT_SIMILARITY:
            return True

        bx, by = best_loc
        current = window[by:by + eh, bx:bx + ew]
        bright_now = float((current >= GLARE_BRIGHT_LEVEL).mean())
        bright_ref = float((patch >= GLARE_BRIGHT_LEVEL).mean())
        if bright_now - bright_ref > GLARE_FRACTION_JUMP:
            return True
    return False


def _detect_blink_liveness(gray_frame, face_box, eye_detectors, liveness_state):
    """
    Strict blink-based liveness detection using OpenCV Haar eye detection.

    The old issue was that Haar eye detection can flicker for a few frames.
    That flicker was sometimes counted as a blink even when the student did not blink.

    This fixed version counts a blink only after this full stable sequence:
    1) eyes visible for several frames
    2) eyes missing/closed for several frames
    3) eyes visible again for several frames

    Face recognition is not allowed to log in until blink_count reaches REQUIRED_BLINKS.
    """
    liveness_state["frames_checked"] += 1

    # Once a valid blink is detected, keep liveness accepted for the rest
    # of this login attempt. Otherwise the stable-frame verification can miss
    # the one exact frame where the blink was counted and later show
    # "Blink not detected" even after attendance was marked.
    if liveness_state.get("blink_count", 0) >= REQUIRED_BLINKS:
        return True, "Liveness Passed", 2

    if liveness_state["frames_checked"] >= LIVENESS_TIMEOUT_FRAMES:
        liveness_state["failed"] = True
        return False, "Blink not detected", 0

    x, y, w, h = face_box
    face_gray = gray_frame[y:y + h, x:x + w]
    if face_gray.size == 0:
        return False, "Keep face centered", 0

    # A real blink happens with a still head. If the head is turning or
    # moving, Haar eye detection drops out and would be miscounted as a
    # blink, so restart the sequence whenever the face box moves too much.
    face_center = (x + w / 2.0, y + h / 2.0)
    last_center = liveness_state.get("last_face_center")
    liveness_state["last_face_center"] = face_center
    if last_center is not None:
        movement = hypot(face_center[0] - last_center[0], face_center[1] - last_center[1])
        if movement > w * HEAD_MOVE_TOLERANCE:
            # Skip this frame without restarting: the Haar face box jumps
            # for a frame exactly when the eyes close, and restarting here
            # cancelled the student's own blink. Sustained movement is
            # caught by the anchor drift check below.
            return False, "Hold your head still", 0

    anchor = liveness_state.get("blink_anchor")
    if anchor is not None:
        drift = hypot(face_center[0] - anchor[0], face_center[1] - anchor[1])
        if drift > w * HEAD_DRIFT_TOLERANCE:
            _reset_blink_phase(liveness_state)
            return False, "Hold your head still", 0

    upper_face = face_gray[0:max(1, h // 2), :]

    try:
        regular_cascade, glasses_cascade = eye_detectors
        eyes = regular_cascade.detectMultiScale(
            upper_face,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(22, 14)
        )
        eye_count = _count_real_eyes(eyes, upper_face.shape[1])
        if eye_count < 2:
            # Eyeglass lenses and glare often hide open eyes from the
            # regular cascade; retry with the eyeglasses-trained one. Kept
            # stricter (minNeighbors 6) because this cascade also fires on
            # glare and frame edges while the eyes are closed, which would
            # make a blink invisible.
            glasses_eyes = glasses_cascade.detectMultiScale(
                upper_face,
                scaleFactor=1.1,
                minNeighbors=6,
                minSize=(22, 14)
            )
            glasses_count = _count_real_eyes(glasses_eyes, upper_face.shape[1])
            if glasses_count > eye_count:
                eye_count = glasses_count
                eyes = glasses_eyes
    except Exception:
        return False, "Eye detector loading", 0

    eyes_visible = eye_count >= 2

    # Exactly one eye found is ambiguous: with glasses, glare regularly hides
    # one eye even when both are open. Hold the sequence in place instead of
    # restarting it; the motion guards above still block head-turn spoofing.
    if eye_count == 1:
        return False, "Look straight at the camera", 1

    if eyes_visible:
        liveness_state["open_eye_frames"] += 1
        # Keep a fresh snapshot of how the open eyes look, so a sudden
        # "no eyes found" frame can be verified as a real blink below.
        liveness_state["eye_templates"] = _capture_eye_templates(upper_face, eyes)

        # Let the drift anchor slowly follow the face while the eyes are
        # open: sitting drift is innocent. It stays frozen from the moment
        # the eyes disappear until the blink completes.
        anchor = liveness_state.get("blink_anchor")
        if anchor is not None and not liveness_state.get("waiting_for_reopen", False):
            liveness_state["blink_anchor"] = (
                anchor[0] + (face_center[0] - anchor[0]) * ANCHOR_FOLLOW_RATE,
                anchor[1] + (face_center[1] - anchor[1]) * ANCHOR_FOLLOW_RATE
            )

        # After a valid closed-eye period, require the eyes to reopen for
        # several consecutive frames. This prevents one noisy frame from
        # being accepted as a blink.
        if liveness_state.get("waiting_for_reopen", False):
            liveness_state["reopen_eye_frames"] += 1

            if liveness_state["reopen_eye_frames"] >= REOPEN_EYE_FRAMES_REQUIRED:
                liveness_state["blink_count"] += 1
                liveness_state["waiting_for_reopen"] = False
                liveness_state["ready_for_blink"] = False
                liveness_state["closed_eye_frames"] = 0
                liveness_state["open_eye_frames"] = 0
                liveness_state["reopen_eye_frames"] = 0

                if liveness_state["blink_count"] >= REQUIRED_BLINKS:
                    return True, "Liveness Passed", eye_count

                return False, "Blink once", eye_count

            return False, "Open eyes after blink", eye_count

        # The user must first show open eyes clearly before the system is
        # allowed to treat missing eyes as the closed part of a blink.
        if liveness_state["open_eye_frames"] >= OPEN_EYE_FRAMES_REQUIRED:
            liveness_state["ready_for_blink"] = True
            if liveness_state.get("blink_anchor") is None:
                liveness_state["blink_anchor"] = face_center
            return False, "Now blink once", eye_count

        return False, "Show both eyes clearly", eye_count

    # Eyes are not visible. Count this as the closed part only after stable
    # open eyes were already detected.
    liveness_state["open_eye_frames"] = 0
    liveness_state["reopen_eye_frames"] = 0

    if liveness_state.get("ready_for_blink", False):
        # Haar can lose open eyes for a frame (glasses glare, noise). Only
        # count this frame as closed eyes when the pixel evidence agrees:
        # both eye regions changed, and not into a bright glare flash.
        # The distinct message makes this check visible while testing.
        if _not_a_real_blink(upper_face, liveness_state.get("eye_templates")):
            return False, "Blink again please", 0

        liveness_state["closed_eye_frames"] += 1

        if liveness_state["closed_eye_frames"] > MAX_CLOSED_EYE_FRAMES:
            liveness_state["closed_eye_frames"] = 0
            liveness_state["ready_for_blink"] = False
            liveness_state["waiting_for_reopen"] = False
            return False, "Blink was too long. Try again", eye_count

        if liveness_state["closed_eye_frames"] >= CLOSED_EYE_FRAMES_REQUIRED:
            liveness_state["waiting_for_reopen"] = True
            return False, "Open your eyes", eye_count

        return False, "Keep blinking", eye_count

    liveness_state["closed_eye_frames"] = 0
    liveness_state["waiting_for_reopen"] = False
    return False, "Show both eyes clearly", eye_count

def is_valid_email(email):
    return re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email or "") is not None


def send_verification_code_to_email(student_email):
    sender_email = os.getenv("SMTP_EMAIL", "").strip()
    sender_password = os.getenv("SMTP_PASSWORD", "").strip()
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com").strip()
    smtp_port = int(os.getenv("SMTP_PORT", "587"))

    if not sender_email or not sender_password:
        messagebox.showerror(
            "SMTP Not Configured",
            "Real email sending is not configured.\n\n"
            "Please set SMTP_EMAIL and SMTP_PASSWORD first.\n"
            "The verification code will not be shown locally."
        )
        return False

    code = str(random.randint(100000, 999999))

    message = EmailMessage()
    message["Subject"] = "Smart Attendance Verification Code"
    message["From"] = sender_email
    message["To"] = student_email
    message.set_content(
        "Smart Attendance System\n\n"
        f"Your verification code is: {code}\n\n"
        "Enter this code in the application to complete your check-in.\n"
        "The code is valid for 5 minutes.\n"
        "If you did not request this code, please ignore this email."
    )

    try:
        with smtplib.SMTP(smtp_server, smtp_port, timeout=20) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.send_message(message)

        verification_codes[student_email.lower()] = (code, time.time())
        return True

    except Exception as error:
        messagebox.showerror("Email Error", f"Could not send verification email:\n{error}")
        return False


def open_email_verification_window(parent_app=None):
    window = ctk.CTkToplevel(parent_app) if parent_app else ctk.CTk()
    window.geometry("500x370")
    window.title("Email Verification Check In")
    window.grab_set()

    ctk.CTkLabel(window, text="Email Verification Check In", font=("Arial", 24, "bold")).pack(pady=(25, 8))
    ctk.CTkLabel(
        window,
        text="The code will be sent only to the registered student email.",
        font=("Arial", 13),
        text_color="gray"
    ).pack(pady=(0, 15))

    email_entry = ctk.CTkEntry(window, width=340, height=42, placeholder_text="Registered student email")
    email_entry.pack(pady=8)

    code_entry = ctk.CTkEntry(window, width=340, height=42, placeholder_text="Enter the code received by email")
    code_entry.pack(pady=8)

    status_label = ctk.CTkLabel(window, text="", font=("Arial", 13))
    status_label.pack(pady=8)

    def send_code():
        student_email = email_entry.get().strip().lower()
        if not is_valid_email(student_email):
            status_label.configure(text="Enter a valid email address.", text_color="red")
            return

        student = get_student_by_email(student_email)
        if not student:
            status_label.configure(text="This email is not registered.", text_color="red")
            return

        if send_verification_code_to_email(student_email):
            status_label.configure(text="Verification code sent to the registered email.", text_color="#059669")

    def verify_code():
        student_email = email_entry.get().strip().lower()
        entered_code = code_entry.get().strip()

        had_code = student_email in verification_codes
        correct_code = _get_valid_verification_code(student_email)

        if correct_code is None:
            if had_code:
                status_label.configure(
                    text="This code has expired. Request a new one.", text_color="red"
                )
            else:
                status_label.configure(text="Invalid verification code.", text_color="red")
            return

        if entered_code != correct_code:
            status_label.configure(text="Invalid verification code.", text_color="red")
            return

        student = get_student_by_email(student_email)
        if not student:
            status_label.configure(text="Student not found.", text_color="red")
            return

        student_id = student[0]
        result = mark_attendance(student_id)
        print(f"Email verification check-in: Student {student_id} - {result}")
        verification_codes.pop(student_email, None)

        user_py = os.path.join(SCRIPT_DIR, "User.py")
        subprocess.Popen([sys.executable, user_py, str(student_id)], cwd=SCRIPT_DIR)

        # Close the verification popup first. If the main app is destroyed first,
        # Tkinter also destroys child windows and window.destroy() can crash with:
        # TclError: can't invoke "destroy" command: application has been destroyed
        try:
            window.grab_release()
        except Exception:
            pass
        try:
            if window.winfo_exists():
                window.destroy()
        except Exception:
            pass

        if parent_app:
            try:
                if parent_app.winfo_exists():
                    parent_app.after(100, parent_app.destroy)
            except Exception:
                pass

    ctk.CTkButton(window, text="Send Verification Code", width=340, height=40, command=send_code).pack(pady=8)
    ctk.CTkButton(window, text="Verify Code + Check In", width=340, height=40, fg_color="#059669", hover_color="#047857", command=verify_code).pack(pady=8)

    if not parent_app:
        window.mainloop()


def recognize_student_login(app):
    trainer_path = os.path.join(SCRIPT_DIR, "trainer.yml")
    if not os.path.exists(trainer_path):
        messagebox.showerror("Training Error", "trainer.yml was not found. Register and train students first.")
        return

    recognizer = cv2.face.LBPHFaceRecognizer_create()
    recognizer.read(trainer_path)
    face_detector = _face_detector()
    eye_detectors = _eye_detectors()
    camera = _open_camera()
    if not camera.isOpened():
        if messagebox.askyesno("Camera Error", "Camera failed to open. Use email verification instead?"):
            open_email_verification_window(app)
        return

    stable_student_id = None
    stable_count = 0
    center_history = deque(maxlen=FACE_CENTER_HISTORY)
    liveness_state = {
        "closed_eye_frames": 0,
        "open_eye_frames": 0,
        "blink_count": 0,
        "frames_checked": 0,
        "ready_for_blink": False,
        "waiting_for_reopen": False,
        "reopen_eye_frames": 0,
        "failed": False,
        "last_face_center": None,
        "blink_anchor": None,
        "eye_templates": None
    }
    liveness_passed = False
    no_face_frames = 0

    while True:
        ret, frame = camera.read()
        if not ret:
            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        # Haar face detection is the slowest step of this loop. Run it on a
        # half-size frame (~4x faster) so the loop keeps a high frame rate:
        # a fast blink only exists for 1-2 frames and a slow loop misses it.
        small_gray = cv2.resize(gray, (0, 0), fx=0.5, fy=0.5)
        faces = face_detector.detectMultiScale(
            small_gray,
            scaleFactor=1.2,
            minNeighbors=6,
            minSize=(40, 40)
        )
        faces = [(sx * 2, sy * 2, sw * 2, sh * 2) for (sx, sy, sw, sh) in faces]

        if len(faces) == 0:
            stable_student_id = None
            stable_count = 0
            center_history.clear()
            # If the face left the frame mid-blink (e.g. the head turned all
            # the way), the half-finished blink must not complete on return.
            _reset_blink_phase(liveness_state)
            liveness_state["last_face_center"] = None
            no_face_frames += 1
            cv2.putText(frame, "No face detected", (30, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 165, 255), 2)
            if no_face_frames >= NO_FACE_TIMEOUT_FRAMES:
                _safe_close_camera(camera)
                if messagebox.askyesno("Face Not Detected", "The system could not detect your face. Use email verification instead?"):
                    open_email_verification_window(app)
                return
        else:
            no_face_frames = 0

        for (x, y, w, h) in faces:
            face_gray = gray[y:y + h, x:x + w]
            face_roi = cv2.resize(face_gray, FACE_SIZE)

            student_id, confidence = recognizer.predict(face_roi)

            liveness_passed, live_text, current_ear = _detect_blink_liveness(
                gray,
                (x, y, w, h),
                eye_detectors,
                liveness_state
            )

            if liveness_state.get("failed"):
                _safe_close_camera(camera)
                messagebox.showerror(
                    "Liveness Failed",
                    "No valid eye blink was detected. Authentication was rejected."
                )
                return

            if liveness_passed:
                box_color = (0, 255, 0)
            else:
                box_color = (0, 165, 255)

            cv2.rectangle(frame, (x, y), (x + w, y + h), box_color, 2)
            cv2.putText(
                frame,
                f"ID:{student_id} Conf:{int(confidence)}",
                (x, y - 35),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                box_color,
                2
            )
            cv2.putText(
                frame,
                live_text,
                (x, y - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                box_color,
                2
            )

            cv2.putText(
                frame,
                f"Eyes: {current_ear}  Blinks: {liveness_state['blink_count']}/{REQUIRED_BLINKS}",
                (30, 70),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.75,
                box_color,
                2
            )

            if liveness_passed and confidence <= CONFIDENCE_LIMIT and student_exists(student_id):
                if stable_student_id == student_id:
                    stable_count += 1
                else:
                    stable_student_id = student_id
                    stable_count = 1

                cv2.putText(
                    frame,
                    f"Verifying real student {stable_count}/{REQUIRED_STABLE_FRAMES}",
                    (30, 40),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 255, 0),
                    2
                )

                if stable_count >= REQUIRED_STABLE_FRAMES:
                    result = mark_attendance(student_id)
                    print(f"Student Found: {student_id} - {result}")

                    _safe_close_camera(camera)
                    try:
                        if app.winfo_exists():
                            app.destroy()
                    except Exception:
                        pass

                    user_py = os.path.join(SCRIPT_DIR, "User.py")
                    subprocess.Popen([sys.executable, user_py, str(student_id)], cwd=SCRIPT_DIR)
                    return
            else:
                stable_student_id = None
                stable_count = 0

                if not liveness_passed:
                    cv2.putText(
                        frame,
                        "Anti-spoofing active: blink required",
                        (30, 40),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.8,
                        (0, 165, 255),
                        2
                    )
                else:
                    cv2.putText(
                        frame,
                        "Unknown Face",
                        (x, y + h + 25),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.8,
                        (0, 0, 255),
                        2
                    )

            break

        cv2.imshow("Face Recognition Login - Blink Anti Spoofing", frame)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    _safe_close_camera(camera)

def save_student(student_name_entry, student_email_entry, department_entry):
    full_name = student_name_entry.get().strip()
    student_email = student_email_entry.get().strip().lower()
    department = department_entry.get()

    if full_name == "" or student_email == "":
        messagebox.showerror("Error", "Please fill all required fields")
        return

    if not is_valid_email(student_email):
        messagebox.showerror("Invalid Email", "Please enter a valid student email address")
        return

    student_db_id = add_student(full_name, student_email, department)

    dataset_path = os.path.join(SCRIPT_DIR, "dataset")
    student_folder = os.path.join(dataset_path, str(student_db_id))

    # Important: remove any old images for the same ID before capturing new ones.
    if os.path.exists(student_folder):
        shutil.rmtree(student_folder)
    os.makedirs(student_folder, exist_ok=True)

    cap = _open_camera()
    if not cap.isOpened():
        messagebox.showerror("Camera Error", "Camera failed to open")
        return

    detector = _face_detector()
    count = 0

    while count < REGISTRATION_IMAGE_COUNT:
        ret, frame = cap.read()
        if not ret:
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = detector.detectMultiScale(
            gray,
            scaleFactor=1.2,
            minNeighbors=6,
            minSize=(80, 80)
        )

        for (x, y, w, h) in faces:
            face_roi = gray[y:y + h, x:x + w]
            face_roi = cv2.resize(face_roi, FACE_SIZE)

            count += 1
            image_path = os.path.join(student_folder, f"image_{count}.jpg")
            cv2.imwrite(image_path, face_roi)

            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.putText(
                frame,
                f"Captured {count}/{REGISTRATION_IMAGE_COUNT}",
                (30, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.9,
                (0, 255, 0),
                2
            )
            break

        cv2.imshow("Capturing Face Images", frame)
        if cv2.waitKey(100) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()

    if count < 10:
        shutil.rmtree(student_folder, ignore_errors=True)
        messagebox.showerror("Capture Error", "Not enough face images captured. Try again with better lighting.")
        return

    student_name_entry.delete(0, "end")
    student_email_entry.delete(0, "end")

    # Retrain immediately, not in the background, so login uses the newest model.
    train_py = os.path.join(SCRIPT_DIR, "Train.py")
    if os.path.exists(train_py):
        subprocess.run([sys.executable, train_py], cwd=SCRIPT_DIR, check=False)

    messagebox.showinfo(
        "Success",
        f"Student registered successfully\nStudent ID: {student_db_id}\nCaptured Images: {count}"
    )


def face_login_system(recognized_student_id, app):
    student = student_exists(recognized_student_id)

    if student:
        app.destroy()
        user_py = os.path.join(SCRIPT_DIR, "User.py")
        subprocess.Popen([sys.executable, user_py, str(recognized_student_id)], cwd=SCRIPT_DIR)
    else:
        print("Student Not Registered")
