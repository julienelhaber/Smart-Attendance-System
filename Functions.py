from database import add_student, mark_attendance, student_exists, get_student_by_email
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
from email.message import EmailMessage
from collections import deque
from math import hypot

try:
    import face_recognition
except ImportError:
    face_recognition = None

FACE_SIZE = (200, 200)
CONFIDENCE_LIMIT = 70
REQUIRED_STABLE_FRAMES = 5

# EAR anti-spoofing settings.
# EAR means Eye Aspect Ratio. It becomes smaller when the eye is closed.
# The login will not be accepted until the system detects a real blink.
EAR_THRESHOLD = 0.21
EAR_CONSECUTIVE_FRAMES = 2
REQUIRED_BLINKS = 1
LIVENESS_TIMEOUT_FRAMES = 350
FACE_CENTER_HISTORY = 20
NO_FACE_TIMEOUT_FRAMES = 250

verification_codes = {}


def _open_camera():
    # Try several Windows camera backends. This prevents the webcam from getting
    # stuck when one backend locks the device.
    for backend in (cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY):
        camera = cv2.VideoCapture(0, backend)
        if camera.isOpened():
            camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            return camera
        camera.release()

    # Try camera index 1 in case Windows assigned the webcam there.
    for backend in (cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY):
        camera = cv2.VideoCapture(1, backend)
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


def _eye_detector():
    return cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_eye.xml"
    )


def _point_distance(point_a, point_b):
    """Calculate the Euclidean distance between two eye landmark points."""
    return hypot(point_a[0] - point_b[0], point_a[1] - point_b[1])


def _eye_aspect_ratio(eye_points):
    """
    Calculate EAR (Eye Aspect Ratio) from 6 eye landmark points.

    Formula:
        EAR = (||p2-p6|| + ||p3-p5||) / (2 * ||p1-p4||)

    When the eye is open, EAR is higher.
    When the eye is closed during a blink, EAR becomes lower.
    """
    if len(eye_points) < 6:
        return None

    vertical_1 = _point_distance(eye_points[1], eye_points[5])
    vertical_2 = _point_distance(eye_points[2], eye_points[4])
    horizontal = _point_distance(eye_points[0], eye_points[3])

    if horizontal == 0:
        return None

    return (vertical_1 + vertical_2) / (2.0 * horizontal)


def _eye_box_to_points(ex, ey, ew, eh):
    """
    Convert an OpenCV eye rectangle into 6 approximate eye points.
    This lets the project use the EAR formula without heavy dlib landmark files.
    """
    return [
        (ex, ey + eh // 2),
        (ex + ew // 4, ey),
        (ex + (3 * ew) // 4, ey),
        (ex + ew, ey + eh // 2),
        (ex + (3 * ew) // 4, ey + eh),
        (ex + ew // 4, ey + eh),
    ]


def _detect_ear_liveness(gray_frame, face_box, eye_detector, liveness_state):
    """
    OpenCV-only EAR-based liveness detection.

    Why this version is used:
    - It opens the camera normally on most Windows laptops.
    - It does not need dlib, scipy, or shape_predictor_68_face_landmarks.dat.
    - It still uses the EAR formula by approximating eye landmark points from
      OpenCV's detected eye boxes.

    Blink logic:
    1. Eyes are visible: calculate EAR and mark that the system saw open eyes.
    2. Eyes disappear after being visible: treat this as closed-eye frames.
    3. Eyes appear again after closed frames: count one blink.
    """
    x, y, w, h = face_box
    face_gray = gray_frame[y:y + h, x:x + w]

    eyes = eye_detector.detectMultiScale(
        face_gray,
        scaleFactor=1.1,
        minNeighbors=5,
        minSize=(20, 20)
    )

    liveness_state["frames_checked"] += 1

    # Keep only the two biggest eye detections.
    eyes = sorted(eyes, key=lambda e: e[2] * e[3], reverse=True)[:2]

    if len(eyes) >= 2:
        ears = []
        for (ex, ey, ew, eh) in eyes:
            eye_points = _eye_box_to_points(ex, ey, ew, eh)
            ear_value = _eye_aspect_ratio(eye_points)
            if ear_value is not None:
                ears.append(ear_value)

        if ears:
            ear = sum(ears) / len(ears)
            liveness_state["last_ear"] = ear
            liveness_state["eyes_seen"] = True

            if liveness_state["closed_eye_frames"] >= EAR_CONSECUTIVE_FRAMES:
                liveness_state["blink_count"] += 1

            liveness_state["closed_eye_frames"] = 0

            if liveness_state["blink_count"] >= REQUIRED_BLINKS:
                return True, "Liveness Passed", ear

            return False, "Blink once", ear

    # If eyes were seen before and now not detected, consider this eye closure.
    if liveness_state.get("eyes_seen"):
        liveness_state["closed_eye_frames"] += 1
        liveness_state["last_ear"] = 0.0
        return False, "Blink detected... open eyes", 0.0

    if liveness_state["frames_checked"] >= LIVENESS_TIMEOUT_FRAMES:
        return False, "Eyes not clear - try again", None

    return False, "Show eyes clearly", None


def is_valid_email(email):
    return re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email or "") is not None


def send_verification_code_to_email(student_email):
    """
    Send a one-time verification code to the student's registered email only.

    Required sender configuration:
        SMTP_EMAIL=your_sender_email@gmail.com
        SMTP_PASSWORD=your_gmail_app_password
        SMTP_SERVER=smtp.gmail.com
        SMTP_PORT=587

    The verification code is never shown inside the application window.
    It is saved temporarily only after the email is sent successfully.
    """
    sender_email = "insertyouremail@gmail.com"
    sender_password = "app generator password"
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
        "If you did not request this code, please ignore this email."
    )

    try:
        with smtplib.SMTP(smtp_server, smtp_port, timeout=20) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.send_message(message)

        verification_codes[student_email.lower()] = code
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
        correct_code = verification_codes.get(student_email)

        if not correct_code or entered_code != correct_code:
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

        subprocess.Popen([sys.executable, "User.py", str(student_id)])

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
    if not os.path.exists("trainer.yml"):
        messagebox.showerror("Training Error", "trainer.yml was not found. Register and train students first.")
        return

    recognizer = cv2.face.LBPHFaceRecognizer_create()
    recognizer.read("trainer.yml")
    face_detector = _face_detector()
    eye_detector = _eye_detector()
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
        "blink_count": 0,
        "frames_checked": 0,
        "last_ear": None,
        "eyes_seen": False
    }
    liveness_passed = False
    no_face_frames = 0

    while True:
        ret, frame = camera.read()
        if not ret:
            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_detector.detectMultiScale(
            gray,
            scaleFactor=1.2,
            minNeighbors=6,
            minSize=(80, 80)
        )

        if len(faces) == 0:
            stable_student_id = None
            stable_count = 0
            center_history.clear()
            no_face_frames += 1
            cv2.putText(frame, "No face detected", (30, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 165, 255), 2)
            if no_face_frames >= NO_FACE_TIMEOUT_FRAMES:
                camera.release()
                cv2.destroyAllWindows()
                if messagebox.askyesno("Face Not Detected", "The system could not detect your face. Use email verification instead?"):
                    open_email_verification_window(app)
                return
        else:
            no_face_frames = 0

        for (x, y, w, h) in faces:
            face_gray = gray[y:y + h, x:x + w]
            face_roi = cv2.resize(face_gray, FACE_SIZE)

            student_id, confidence = recognizer.predict(face_roi)

            liveness_passed, live_text, current_ear = _detect_ear_liveness(
                gray,
                (x, y, w, h),
                eye_detector,
                liveness_state
            )

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

            if current_ear is not None:
                cv2.putText(
                    frame,
                    f"EAR: {current_ear:.2f}  Blinks: {liveness_state['blink_count']}/{REQUIRED_BLINKS}",
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

                    camera.release()
                    cv2.destroyAllWindows()
                    app.destroy()

                    subprocess.Popen([
                        sys.executable,
                        "User.py",
                        str(student_id)
                    ])
                    return
            else:
                stable_student_id = None
                stable_count = 0

                if not liveness_passed:
                    cv2.putText(
                        frame,
                        "EAR anti-spoofing active: blink required",
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

        cv2.imshow("Face Recognition Login - EAR Anti Spoofing", frame)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    camera.release()
    cv2.destroyAllWindows()

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

    dataset_path = "dataset"
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

    while count < 40:
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
                f"Captured {count}/40",
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
    if os.path.exists("Train.py"):
        subprocess.run([sys.executable, "Train.py"], check=False)

    messagebox.showinfo(
        "Success",
        f"Student registered successfully\nStudent ID: {student_db_id}\nCaptured Images: {count}"
    )


def face_login_system(recognized_student_id, app):
    student = student_exists(recognized_student_id)

    if student:
        app.destroy()
        subprocess.Popen([sys.executable, "User.py", str(recognized_student_id)])
    else:
        print("Student Not Registered")
