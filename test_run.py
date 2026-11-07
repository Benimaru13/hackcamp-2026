import cv2
import mediapipe as mp
from gesture_detector import HandGestureDetector
print("🔍 揪出 MediaPipe 的真实路径:", mp.__file__)

def main():
    # 1. 实例化你刚刚写好的检测器对象 (自动拥有了 self 里的所有配置)
    detector = HandGestureDetector()
    
    # 2. 打开 Mac 自带的摄像头 (0 代表默认摄像头)
    cap = cv2.VideoCapture(0)

    print("摄像头已启动！按键盘 'q' 键退出程序。")

    while True:
        # 3. 不断读取摄像头的每一帧画面
        success, frame = cap.read()
        if not success:
            print("无法获取画面")
            break
            
        # 4. 把原始画面喂给你写的 detector
        annotated_frame, result_data = detector.process_frame(frame)
        
        # 5. 在视频窗口上打印出当前识别到的手势，方便调试
        gesture = result_data["gesture"]
        cv2.putText(annotated_frame, f"Gesture: {gesture}", (10, 50), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        
        # 6. 显示处理好的画面
        cv2.imshow("HackCamp Hand Tracker Demo", annotated_frame)
        
        # 7. 按 'q' 键退出循环
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    # 释放摄像头资源并关掉窗口
    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()