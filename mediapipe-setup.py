import cv2

cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("Cannot access webcam!")
    exit()

print("Webcam successfully initialized!")

while True:
    success, frame = cap.read()

    if not success:
        print("Cannot read webcam frame!")
        break

    cv2.imshow("AirTracker Webcam", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
