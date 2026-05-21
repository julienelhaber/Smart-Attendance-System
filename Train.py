import cv2
import os
import numpy as np
from PIL import Image

DATASET_PATH = "dataset"
TRAINER_FILE = "trainer.yml"
FACE_SIZE = (200, 200)

faces = []
ids = []

if not os.path.exists(DATASET_PATH):
    os.makedirs(DATASET_PATH)

for student_id in sorted(os.listdir(DATASET_PATH), key=lambda x: int(x) if x.isdigit() else 999999):
    if not student_id.isdigit():
        continue

    student_folder = os.path.join(DATASET_PATH, student_id)
    if not os.path.isdir(student_folder):
        continue

    for image_name in os.listdir(student_folder):
        image_path = os.path.join(student_folder, image_name)

        try:
            image = Image.open(image_path).convert("L")
            image = image.resize(FACE_SIZE)
            image_np = np.array(image, "uint8")

            faces.append(image_np)
            ids.append(int(student_id))
        except Exception:
            pass

if len(faces) == 0:
    print("No face images found. Training skipped.")
else:
    recognizer = cv2.face.LBPHFaceRecognizer_create(
        radius=1,
        neighbors=8,
        grid_x=8,
        grid_y=8
    )

    recognizer.train(faces, np.array(ids))
    recognizer.save(TRAINER_FILE)

    print(f"Training Complete. Images trained: {len(faces)}")
