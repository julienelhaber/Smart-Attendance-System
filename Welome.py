import customtkinter as ctk
from Functions import recognize_student_login, open_email_verification_window
import subprocess


# ---------------- APP ----------------
app = ctk.CTk()
app.geometry("1200x700")
app.title("Smart Attendance System")

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue") 


# ---------------- FUNCTIONS ----------------
def admin_login():

    username = username_entry.get()
    password = password_entry.get()

    if username == "admin" and password == "1234":

        app.destroy()

        subprocess.Popen(["python", "Main.py"])

    else:

        status_label.configure(
            text="Wrong Username or Password",
            text_color="red"
        )



# ---------------- WELCOME FRAME ----------------
welcome_frame = ctk.CTkFrame(app)
welcome_frame.pack(fill="both", expand=True)


# Left Side
left_frame = ctk.CTkFrame(
    welcome_frame,
    fg_color="#1E293B",
    corner_radius=0
)
left_frame.pack(side="left", fill="both", expand=True)


title_label = ctk.CTkLabel(
    left_frame,
    text="SMART\nATTENDANCE\nSYSTEM",
    font=("Arial", 42, "bold"),
    text_color="white",
    justify="left"
)
title_label.place(relx=0.15, rely=0.3)


desc_label = ctk.CTkLabel(
    left_frame,
    text="Final Year Project\nFace Recognition Attendance System",
    font=("Arial", 18),
    text_color="lightgray",
    justify="left"
)
desc_label.place(relx=0.15, rely=0.6)


# Right Side
right_frame = ctk.CTkFrame(
    welcome_frame,
    fg_color="#0F172A",
    corner_radius=0
)
right_frame.pack(side="right", fill="both", expand=True)


login_title = ctk.CTkLabel(
    right_frame,
    text="Admin Login",
    font=("Arial", 32, "bold")
)
login_title.place(relx=0.32, rely=0.15)


username_entry = ctk.CTkEntry(
    right_frame,
    width=300,
    height=45,
    placeholder_text="Username"
)
username_entry.place(relx=0.25, rely=0.3)


password_entry = ctk.CTkEntry(
    right_frame,
    width=300,
    height=45,
    placeholder_text="Password",
    show="*"
)
password_entry.place(relx=0.25, rely=0.4)


login_button = ctk.CTkButton(
    right_frame,
    text="Login",
    width=300,
    height=45,
    font=("Arial", 16, "bold"),
    command=admin_login
)
login_button.place(relx=0.25, rely=0.52)


or_label = ctk.CTkLabel(
    right_frame,
    text="OR",
    font=("Arial", 18, "bold")
)
or_label.place(relx=0.47, rely=0.64)


face_button = ctk.CTkButton(
    right_frame,
    text="Login with Face Recognition",
    width=300,
    height=45,
    fg_color="#059669",
    hover_color="#047857",
    font=("Arial", 16, "bold"),
    command=lambda: recognize_student_login(app)
)
face_button.place(relx=0.25, rely=0.70)

email_button = ctk.CTkButton(
    right_frame,
    text="Use Email Verification Code",
    width=300,
    height=45,
    fg_color="#2563EB",
    hover_color="#1D4ED8",
    font=("Arial", 16, "bold"),
    command=lambda: open_email_verification_window(app)
)
email_button.place(relx=0.25, rely=0.80)


status_label = ctk.CTkLabel(
    right_frame,
    text="",
    font=("Arial", 14)
)
status_label.place(relx=0.3, rely=0.90)


# ---------------- DASHBOARD FRAME ----------------
dashboard_frame = ctk.CTkFrame(app)

dashboard_label = ctk.CTkLabel(
    dashboard_frame,
    text="Dashboard",
    font=("Arial", 40, "bold")
)
dashboard_label.pack(pady=50)


# ---------------- RUN APP ----------------
app.mainloop()